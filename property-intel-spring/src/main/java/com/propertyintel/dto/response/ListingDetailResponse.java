package com.propertyintel.dto.response;

import lombok.Data;

import java.time.LocalDateTime;

@Data
public class ListingDetailResponse {
    private Integer id;
    private String sourceId;
    private String title;
    private String descriptionRaw;
    private Long priceVnd;
    private Float areaM2;
    private Float areaMinM2;
    private Float areaMaxM2;
    private String district;
    private String addressText;
    private Float lat;
    private Float lng;
    private String contactPhone;
    private String shortDescription;
    private String longDescription;
    private String priceNote;
    private LocalDateTime postedAt;

    // Các trường JSONB (để dạng String hoặc Object tùy bạn thiết kế, tạm thời để String để nhận nguyên cục JSON)
    private String amenitiesJson;
    private String nearLandmarksJson;
    private String commonAmenitiesJson;
    private String roomLayoutTagsJson;
    private String serviceFeesJson;
    private String buildingJson;
    private String imagesJson;
}